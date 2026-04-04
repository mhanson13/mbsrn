"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { WorkflowSiteSelector } from "./layout/WorkflowSiteSelector";
import { useOperatorContext } from "./useOperatorContext";
import { logoutSession } from "../lib/api/client";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/sites", label: "Sites" },
  { href: "/audits", label: "Audit Runs" },
  { href: "/competitors", label: "Competitors" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/automation", label: "Automation" },
  { href: "/business-profile", label: "Business Profile" },
  { href: "/admin", label: "Admin", adminOnly: true },
  { href: "/user-mgmt", label: "User Mgmt", adminOnly: true },
];

type ShellWidthMode = "default" | "wide" | "full";
type ThemeMode = "light" | "dark";

const OPERATOR_UI_THEME_STORAGE_KEY = "operator-ui-theme";

const WORKFLOW_SITE_SELECTOR_PATH_PREFIXES = [
  "/dashboard",
  "/sites",
  "/audits",
  "/competitors",
  "/recommendations",
  "/automation",
  "/business-profile",
] as const;

function resolveShellWidthMode(pathname: string): ShellWidthMode {
  if (pathname.startsWith("/sites/")) {
    return "full";
  }
  if (pathname === "/dashboard") {
    return "default";
  }
  return "wide";
}

function shouldShowWorkflowSiteSelector(pathname: string): boolean {
  return WORKFLOW_SITE_SELECTOR_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark";
}

function parseSiteIdFromSitePath(pathname: string): string | null {
  if (!pathname.startsWith("/sites/")) {
    return null;
  }
  const suffix = pathname.slice("/sites/".length);
  if (!suffix || suffix.includes("/")) {
    return null;
  }
  try {
    return decodeURIComponent(suffix);
  } catch {
    return suffix;
  }
}

function WorkflowHeaderSiteSelector({ pathname }: { pathname: string }) {
  const context = useOperatorContext();
  const {
    loading: contextLoading,
    error: contextError,
    scopeWarning: contextScopeWarning,
    businessId: contextBusinessId,
    sites: contextSites,
    selectedSiteId: contextSelectedSiteId,
    setSelectedSiteId: setContextSelectedSiteId,
  } = context;
  const router = useRouter();
  const searchParams = useSearchParams();
  const [scopeNotice, setScopeNotice] = useState<string | null>(null);
  const searchParamsString = searchParams?.toString() || "";
  const authorizedSites = useMemo(
    () => contextSites.filter((site) => site.business_id === contextBusinessId),
    [contextBusinessId, contextSites],
  );
  const selectedSite = authorizedSites.find((site) => site.id === contextSelectedSiteId) || null;
  const effectiveSelectedSiteId = selectedSite?.id || authorizedSites[0]?.id || null;
  const activeBusinessId = selectedSite?.business_id || contextBusinessId || "";
  const contextWarning = contextScopeWarning || null;

  useEffect(() => {
    if (contextLoading || contextError || authorizedSites.length === 0 || !effectiveSelectedSiteId) {
      return;
    }
    if (effectiveSelectedSiteId !== contextSelectedSiteId) {
      setContextSelectedSiteId(effectiveSelectedSiteId);
    }
  }, [
    authorizedSites.length,
    contextError,
    contextLoading,
    contextSelectedSiteId,
    setContextSelectedSiteId,
    effectiveSelectedSiteId,
  ]);

  useEffect(() => {
    if (contextLoading || contextError || authorizedSites.length === 0 || !effectiveSelectedSiteId) {
      setScopeNotice(null);
      return;
    }

    const authorizedSiteIds = new Set(authorizedSites.map((site) => site.id));
    const requestedSiteIdFromPath = parseSiteIdFromSitePath(pathname);
    const currentParams = new URLSearchParams(searchParamsString);
    const requestedSiteIdFromQuery = (currentParams.get("site_id") || "").trim();

    let nextPath: string | null = null;
    if (requestedSiteIdFromPath && !authorizedSiteIds.has(requestedSiteIdFromPath)) {
      nextPath = `/sites/${encodeURIComponent(effectiveSelectedSiteId)}`;
    } else if (requestedSiteIdFromQuery && !authorizedSiteIds.has(requestedSiteIdFromQuery)) {
      currentParams.set("site_id", effectiveSelectedSiteId);
      const query = currentParams.toString();
      nextPath = query ? `${pathname}?${query}` : pathname;
    }

    if (!nextPath) {
      setScopeNotice(null);
      return;
    }

    setScopeNotice("Requested site is outside your authorized workspace scope. Showing an authorized site instead.");

    if (typeof window === "undefined") {
      router.replace(nextPath);
      return;
    }

    const currentPathWithQuery = `${window.location.pathname}${window.location.search}`;
    if (currentPathWithQuery !== nextPath) {
      router.replace(nextPath);
    }
  }, [
    authorizedSites,
    contextError,
    contextLoading,
    effectiveSelectedSiteId,
    pathname,
    router,
    searchParamsString,
  ]);

  if (
    !shouldShowWorkflowSiteSelector(pathname)
    || contextLoading
    || !!contextError
    || !activeBusinessId
  ) {
    return null;
  }

  function handleSiteChange(siteId: string) {
    if (!siteId) {
      return;
    }
    setContextSelectedSiteId(siteId);

    if (pathname.startsWith("/sites/")) {
      const nextPath = `/sites/${encodeURIComponent(siteId)}`;
      if (typeof window === "undefined" || window.location.pathname !== nextPath) {
        router.replace(nextPath);
      }
      return;
    }

    const currentParams = new URLSearchParams(searchParams?.toString() || "");
    currentParams.set("site_id", siteId);
    const query = currentParams.toString();
    const nextPath = query ? `${pathname}?${query}` : pathname;
    if (typeof window === "undefined") {
      router.replace(nextPath);
      return;
    }
    const currentPathWithQuery = `${window.location.pathname}${window.location.search}`;
    if (currentPathWithQuery !== nextPath) {
      router.replace(nextPath);
    }
  }

  return (
    <div className="topnav-context-row" data-testid="topnav-site-selector-row">
      <div className="topnav-context-inner">
        <WorkflowSiteSelector
          id="global-workflow-site-selector"
          sites={authorizedSites}
          selectedSiteId={effectiveSelectedSiteId}
          onChange={handleSiteChange}
          className="topnav-site-selector"
        />
        <div className="topnav-context-meta" data-testid="topnav-context-identifiers">
          <span className="topnav-context-meta-item">
            Site ID: <code>{selectedSite?.id || "—"}</code>
          </span>
          <span className="topnav-context-meta-item">
            Business ID: <code>{activeBusinessId || "—"}</code>
          </span>
        </div>
        {scopeNotice || contextWarning ? (
          <p className="topnav-context-warning hint muted" data-testid="topnav-context-warning">
            {scopeNotice || contextWarning}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { token, refreshToken, principal, clearSession } = useAuth();
  const [isMounted, setIsMounted] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode | null>(null);
  const resolvedPrincipal = isMounted ? principal : null;
  const showWorkflowSiteSelector = Boolean(
    resolvedPrincipal?.business_id && token && shouldShowWorkflowSiteSelector(pathname),
  );
  const shellWidthMode = resolveShellWidthMode(pathname);
  const shellMainInnerClassName = [
    "operator-shell-main-inner",
    shellWidthMode === "default" ? "" : `operator-shell-main-inner-${shellWidthMode}`,
  ]
    .filter(Boolean)
    .join(" ");

  async function handleSignOut() {
    try {
      if (token) {
        await logoutSession(token, refreshToken || undefined);
      }
    } catch {
      // Clear local session state even when backend logout fails.
    } finally {
      clearSession();
    }
  }

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const storedTheme = window.localStorage.getItem(OPERATOR_UI_THEME_STORAGE_KEY);
      if (!isThemeMode(storedTheme)) {
        return;
      }
      document.documentElement.dataset.theme = storedTheme;
      setThemeMode(storedTheme);
    } catch {
      // Keep default appearance when local storage is unavailable.
    }
  }, []);

  const handleThemeToggle = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const currentTheme =
      themeMode
      || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const nextTheme: ThemeMode = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    setThemeMode(nextTheme);
    try {
      window.localStorage.setItem(OPERATOR_UI_THEME_STORAGE_KEY, nextTheme);
    } catch {
      // Keep toggled theme in memory when local storage is unavailable.
    }
  }, [themeMode]);

  return (
    <>
      <header className="topnav">
        <div className="topnav-inner">
          <div className="topnav-brand">
            <strong>MBSRN Operator Workspace</strong>
          </div>
          <nav className="topnav-links">
            {links
              .filter((link) => !link.adminOnly || resolvedPrincipal?.role === "admin")
              .map((link) => {
                const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={active ? "topnav-link is-active" : "topnav-link"}
                    aria-current={active ? "page" : undefined}
                  >
                    {link.label}
                  </Link>
                );
              })}
          </nav>
          <div className="topnav-session">
            <small className="topnav-principal">
              {resolvedPrincipal ? `${resolvedPrincipal.display_name} (${resolvedPrincipal.role})` : "Account"}
            </small>
            <button
              type="button"
              className="topnav-theme-toggle"
              onClick={handleThemeToggle}
              data-testid="topnav-theme-toggle"
            >
              Light / Dark
            </button>
            {resolvedPrincipal ? (
              <>
                <button type="button" onClick={() => void handleSignOut()}>
                  Sign out
                </button>
              </>
            ) : (
              <Link href="/" className="topnav-link">
                Sign in
              </Link>
            )}
          </div>
        </div>
        {showWorkflowSiteSelector ? <WorkflowHeaderSiteSelector pathname={pathname} /> : null}
      </header>
      <main className="operator-shell-main">
        <div className={shellMainInnerClassName}>{children}</div>
      </main>
    </>
  );
}
