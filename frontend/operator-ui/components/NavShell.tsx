"use client";

import Link from "next/link";
import Image from "next/image";
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
  { href: "/google-profile", label: "Google Profile" },
  { href: "/admin", label: "Admin", adminOnly: true },
  { href: "/user-mgmt", label: "User Mgmt", adminOnly: true },
];

type ShellRouteContext = {
  label: string;
  summary: string;
  quickHref: string;
  quickLabel: string;
  badgeClass: "badge-success" | "badge-warn" | "badge-muted" | "badge-error";
};

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
  "/google-profile",
] as const;

function isAliasPath(pathname: string, basePath: string): boolean {
  return pathname === basePath || pathname.startsWith(`${basePath}/`);
}

function isNavLinkActive(pathname: string, href: string): boolean {
  if (isAliasPath(pathname, href)) {
    return true;
  }
  if (href === "/google-profile" && isAliasPath(pathname, "/business-profile")) {
    return true;
  }
  return false;
}

function resolveShellRouteContext(pathname: string): ShellRouteContext {
  if (pathname.startsWith("/sites/")) {
    return {
      label: "Site workspace",
      summary: "Run recommendations, migration, and supporting reviews for one selected site.",
      quickHref: pathname,
      quickLabel: "Open site workspace",
      badgeClass: "badge-success",
    };
  }
  if (pathname === "/sites") {
    return {
      label: "Site inventory",
      summary: "Pick the right site workspace before running audits, recommendations, or migration.",
      quickHref: "/sites",
      quickLabel: "Review sites",
      badgeClass: "badge-muted",
    };
  }
  if (pathname.startsWith("/recommendations/runs/")) {
    return {
      label: "Recommendation run details",
      summary: "Validate run output and narratives, then route decisions back into site execution.",
      quickHref: "/recommendations",
      quickLabel: "Back to recommendations",
      badgeClass: "badge-warn",
    };
  }
  if (pathname.startsWith("/recommendations")) {
    return {
      label: "Recommendations workspace",
      summary: "Prioritize open recommendation work, execute actions, and track run outcomes.",
      quickHref: "/recommendations",
      quickLabel: "Review queue",
      badgeClass: "badge-warn",
    };
  }
  if (pathname.startsWith("/automation")) {
    return {
      label: "Automation oversight",
      summary: "Track current automation status and intervene quickly when run outcomes regress.",
      quickHref: "/automation",
      quickLabel: "View automation",
      badgeClass: "badge-success",
    };
  }
  if (pathname.startsWith("/competitors")) {
    return {
      label: "Competitor context",
      summary: "Use competitive signals to support recommendation prioritization and narrative trust.",
      quickHref: "/competitors",
      quickLabel: "Review competitors",
      badgeClass: "badge-muted",
    };
  }
  if (pathname.startsWith("/audits")) {
    return {
      label: "Audit runs",
      summary: "Check crawl and audit outcomes before triggering recommendation generation.",
      quickHref: "/audits",
      quickLabel: "Review audits",
      badgeClass: "badge-muted",
    };
  }
  if (pathname.startsWith("/google-profile") || pathname.startsWith("/business-profile")) {
    return {
      label: "Google profile",
      summary: "Maintain profile and location context so downstream recommendations stay grounded.",
      quickHref: "/google-profile",
      quickLabel: "Open Google Profile",
      badgeClass: "badge-muted",
    };
  }
  if (pathname.startsWith("/admin") || pathname.startsWith("/user-mgmt")) {
    return {
      label: "Admin and governance",
      summary: "Manage workspace governance, access controls, and operator support settings.",
      quickHref: "/admin",
      quickLabel: "Open admin",
      badgeClass: "badge-error",
    };
  }
  return {
    label: "Dashboard",
    summary: "Review high-signal priorities and launch the next workflow with confidence.",
    quickHref: "/dashboard",
    quickLabel: "Open dashboard",
    badgeClass: "badge-success",
  };
}

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
  const [candidateSiteId] = suffix.split("/", 1);
  if (!candidateSiteId) {
    return null;
  }
  try {
    return decodeURIComponent(candidateSiteId);
  } catch {
    return candidateSiteId;
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
  const requestedSiteIdFromPath = parseSiteIdFromSitePath(pathname);
  const authorizedSites = useMemo(
    () => contextSites.filter((site) => site.business_id === contextBusinessId),
    [contextBusinessId, contextSites],
  );
  const selectedSite = useMemo(() => {
    if (requestedSiteIdFromPath) {
      const routeSite = authorizedSites.find((site) => site.id === requestedSiteIdFromPath);
      if (routeSite) {
        return routeSite;
      }
    }
    return authorizedSites.find((site) => site.id === contextSelectedSiteId) || null;
  }, [authorizedSites, contextSelectedSiteId, requestedSiteIdFromPath]);
  const effectiveSelectedSiteId = selectedSite?.id || authorizedSites[0]?.id || null;
  const effectiveSite = useMemo(
    () => authorizedSites.find((site) => site.id === effectiveSelectedSiteId) || null,
    [authorizedSites, effectiveSelectedSiteId],
  );
  const activeBusinessId = effectiveSite?.business_id || "";
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
    requestedSiteIdFromPath,
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
      const suffix = pathname.slice("/sites/".length);
      const segments = suffix.split("/");
      const remaining = segments.length > 1 ? `/${segments.slice(1).join("/")}` : "";
      const nextPath = `/sites/${encodeURIComponent(siteId)}${remaining}`;
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
            Site ID: <code>{effectiveSite?.id || "—"}</code>
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
  const routeContext = resolveShellRouteContext(pathname);
  const principalRoleLabel = resolvedPrincipal?.role === "admin"
    ? "Admin"
    : resolvedPrincipal?.role === "operator"
      ? "Operator"
      : "Guest";
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
            <Link href="/dashboard" className="topnav-brand-link" data-testid="topnav-logo-link">
              <Image
                src="/images/mbsrn-logo.jpg"
                alt="MBSRN"
                className="topnav-logo"
                width={32}
                height={32}
                data-testid="topnav-logo-image"
              />
              <span className="topnav-brand-content">
                <strong>MBSRN Operator Workspace</strong>
                <span className="topnav-brand-subtitle">
                  Unified control surface for operational workflows
                </span>
              </span>
            </Link>
          </div>
          <div className="topnav-rail" data-testid="topnav-route-rail">
            <nav className="topnav-links">
              {links
                .filter((link) => !link.adminOnly || resolvedPrincipal?.role === "admin")
                .map((link) => {
                  const active = isNavLinkActive(pathname, link.href);
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
            <div className="topnav-route-context" data-testid="topnav-route-context">
              <span className={`badge ${routeContext.badgeClass} topnav-route-badge`}>
                Current area: {routeContext.label}
              </span>
              <p className="topnav-route-summary">{routeContext.summary}</p>
              <Link href={routeContext.quickHref} className="topnav-route-cta">
                {routeContext.quickLabel}
              </Link>
            </div>
          </div>
          <div className="topnav-session">
            <div className="topnav-session-identity">
              <small className="topnav-principal">
                {resolvedPrincipal ? resolvedPrincipal.display_name : "Account"}
              </small>
              <span className="badge badge-muted topnav-role-badge" data-testid="topnav-role-badge">
                {principalRoleLabel}
              </span>
            </div>
            <div className="topnav-session-actions">
              <button
                type="button"
                className="topnav-theme-toggle"
                onClick={handleThemeToggle}
                data-testid="topnav-theme-toggle"
              >
                Light / Dark
              </button>
              {resolvedPrincipal ? (
                <button type="button" onClick={() => void handleSignOut()}>
                  Sign out
                </button>
              ) : (
                <Link href="/" className="topnav-link">
                  Sign in
                </Link>
              )}
            </div>
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
