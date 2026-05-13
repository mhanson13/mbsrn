import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const MULTIPART_CONTENT_TYPE = "multipart/form-data";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH"]);
const NEXT_ACTION_HEADER = "next-action";
const STALE_SERVER_ACTION_MESSAGE =
  "This workspace tab is out of date after a deployment. Refresh and try again.";
const MAX_APP_VERSION_LENGTH = 80;

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

function isStaleServerActionRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(request.method.toUpperCase())) {
    return false;
  }
  if (!request.headers.has(NEXT_ACTION_HEADER)) {
    return false;
  }
  const pathname = request.nextUrl.pathname || "/";
  if (isApiPath(pathname)) {
    return false;
  }
  return true;
}

function isUnsupportedMultipartRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(request.method.toUpperCase())) {
    return false;
  }
  if (request.headers.has(NEXT_ACTION_HEADER)) {
    return false;
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes(MULTIPART_CONTENT_TYPE)) {
    return false;
  }
  const pathname = request.nextUrl.pathname || "/";
  if (isApiPath(pathname)) {
    return false;
  }
  return true;
}

export function middleware(request: NextRequest): NextResponse {
  if (isStaleServerActionRequest(request)) {
    console.warn("[operator-ui] blocked_stale_server_action_request", {
      method: request.method.toUpperCase(),
      pathname: request.nextUrl.pathname || "/",
      classification: "stale_server_action_build_mismatch",
      app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
    });
    return new NextResponse(STALE_SERVER_ACTION_MESSAGE, {
      status: 409,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
        "X-Operator-UI-Error-Classification": "stale_server_action_build_mismatch",
      },
    });
  }

  if (!isUnsupportedMultipartRequest(request)) {
    return NextResponse.next();
  }

  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  console.warn("[operator-ui] blocked_unsupported_multipart_request", {
    method: request.method.toUpperCase(),
    pathname: request.nextUrl.pathname || "/",
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
