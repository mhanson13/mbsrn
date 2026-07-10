import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const MULTIPART_CONTENT_TYPE = "multipart/form-data";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH"]);
const NEXT_ACTION_HEADER = "next-action";
const STALE_SERVER_ACTION_MESSAGE =
  "A new version of MBSRN was deployed. Refresh this page before continuing.";
const OPERATOR_COMPONENT = "operator-ui";
const STALE_SERVER_ACTION_CLASSIFICATION = "stale_server_action_build_mismatch";
const UNSUPPORTED_MULTIPART_CLASSIFICATION = "unsupported_non_api_multipart_request";
const MAX_APP_VERSION_LENGTH = 80;
const STALE_SERVER_ACTION_WARN_THROTTLE_WINDOW_MS = 60_000;
const STALE_SERVER_ACTION_WARN_CACHE_LIMIT = 256;
const staleServerActionWarnTimestamps = new Map<string, number>();

type StructuredRejectionLog = {
  severity: "INFO" | "WARNING";
  component: string;
  event: string;
  method: string;
  pathname: string;
  classification: string;
  app_version: string;
  refresh_required?: boolean;
  has_boundary?: boolean;
};

function sanitizeAppVersion(rawValue: unknown): string {
  if (typeof rawValue !== "string") {
    return "unknown";
  }
  const trimmed = rawValue.trim();
  if (!trimmed || trimmed.length > MAX_APP_VERSION_LENGTH) {
    return "unknown";
  }
  return trimmed;
}

function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

function requestMethod(request: NextRequest): string {
  return request.method.toUpperCase();
}

function requestPathname(request: NextRequest): string {
  return request.nextUrl.pathname || "/";
}

function isStaleServerActionRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(requestMethod(request))) {
    return false;
  }
  if (!request.headers.has(NEXT_ACTION_HEADER)) {
    return false;
  }
  const pathname = requestPathname(request);
  if (isApiPath(pathname)) {
    return false;
  }
  return true;
}

function isUnsupportedMultipartRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(requestMethod(request))) {
    return false;
  }
  if (request.headers.has(NEXT_ACTION_HEADER)) {
    return false;
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes(MULTIPART_CONTENT_TYPE)) {
    return false;
  }
  const pathname = requestPathname(request);
  if (isApiPath(pathname)) {
    return false;
  }
  return true;
}

function buildStaleServerActionWarnKey(request: NextRequest): string {
  const method = requestMethod(request);
  const pathname = requestPathname(request);
  const appVersion = sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION);
  return `${method}:${pathname}:${appVersion}`;
}

function pruneStaleServerActionWarnCache(nowMs: number): void {
  if (staleServerActionWarnTimestamps.size <= STALE_SERVER_ACTION_WARN_CACHE_LIMIT) {
    return;
  }
  for (const [key, timestampMs] of staleServerActionWarnTimestamps.entries()) {
    if (nowMs - timestampMs >= STALE_SERVER_ACTION_WARN_THROTTLE_WINDOW_MS) {
      staleServerActionWarnTimestamps.delete(key);
    }
  }
  if (staleServerActionWarnTimestamps.size <= STALE_SERVER_ACTION_WARN_CACHE_LIMIT) {
    return;
  }
  const entriesByAge = [...staleServerActionWarnTimestamps.entries()].sort((left, right) => left[1] - right[1]);
  const entriesToTrim = staleServerActionWarnTimestamps.size - STALE_SERVER_ACTION_WARN_CACHE_LIMIT;
  for (let index = 0; index < entriesToTrim; index += 1) {
    staleServerActionWarnTimestamps.delete(entriesByAge[index]?.[0] || "");
  }
}

function shouldLogStaleServerActionWarning(request: NextRequest): boolean {
  const nowMs = Date.now();
  const key = buildStaleServerActionWarnKey(request);
  const lastWarnMs = staleServerActionWarnTimestamps.get(key);
  if (
    typeof lastWarnMs === "number"
    && nowMs - lastWarnMs < STALE_SERVER_ACTION_WARN_THROTTLE_WINDOW_MS
  ) {
    return false;
  }
  staleServerActionWarnTimestamps.set(key, nowMs);
  pruneStaleServerActionWarnCache(nowMs);
  return true;
}

// Exported for deterministic middleware tests only.
export function __resetMiddlewareTestState(): void {
  staleServerActionWarnTimestamps.clear();
}

function logControlledRejection(payload: StructuredRejectionLog): void {
  // Emit a single JSON line so Cloud Logging receives one structured record.
  console.log(JSON.stringify(payload));
}

export function middleware(request: NextRequest): NextResponse {
  if (isStaleServerActionRequest(request)) {
    if (shouldLogStaleServerActionWarning(request)) {
      logControlledRejection({
        severity: "INFO",
        component: OPERATOR_COMPONENT,
        event: "blocked_stale_server_action_request",
        method: requestMethod(request),
        pathname: requestPathname(request),
        classification: STALE_SERVER_ACTION_CLASSIFICATION,
        app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
        refresh_required: true,
      });
    }
    return new NextResponse(STALE_SERVER_ACTION_MESSAGE, {
      status: 409,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
        "X-Operator-UI-Error-Classification": STALE_SERVER_ACTION_CLASSIFICATION,
        "X-Operator-UI-Refresh-Required": "true",
      },
    });
  }

  if (!isUnsupportedMultipartRequest(request)) {
    return NextResponse.next();
  }

  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  logControlledRejection({
    severity: "INFO",
    component: OPERATOR_COMPONENT,
    event: "blocked_unsupported_multipart_request",
    method: requestMethod(request),
    pathname: requestPathname(request),
    classification: UNSUPPORTED_MULTIPART_CLASSIFICATION,
    app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
    has_boundary: contentType.includes("boundary="),
  });
  return new NextResponse("Unsupported multipart request.", {
    status: 400,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
