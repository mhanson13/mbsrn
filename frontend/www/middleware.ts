import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const MULTIPART_CONTENT_TYPE = "multipart/form-data";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH"]);
const WWW_COMPONENT = "mbsrn-www";
const UNSUPPORTED_MULTIPART_CLASSIFICATION = "unsupported_non_api_multipart_request";
const UNSUPPORTED_PUBLIC_POST_CLASSIFICATION = "unsupported_non_api_post_request";
const MAX_APP_VERSION_LENGTH = 80;

type StructuredLog = {
  severity: "INFO" | "ERROR";
  component: string;
  event: string;
  method: string;
  pathname: string;
  classification: string;
  app_version: string;
  has_boundary?: boolean;
  error_message?: string;
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

function requestMethod(request: NextRequest): string {
  return request.method.toUpperCase();
}

function requestPathname(request: NextRequest): string {
  return request.nextUrl.pathname || "/";
}

function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

function isMultipartContentType(contentType: string): boolean {
  return contentType.includes(MULTIPART_CONTENT_TYPE);
}

function logStructured(payload: StructuredLog): void {
  // Emit one JSON line per controlled rejection/event.
  const serialized = JSON.stringify(payload);
  if (payload.severity === "ERROR") {
    console.error(serialized);
    return;
  }
  console.log(serialized);
}

function isUnsupportedMultipartRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(requestMethod(request))) {
    return false;
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!isMultipartContentType(contentType)) {
    return false;
  }
  const pathname = requestPathname(request);
  if (isApiPath(pathname)) {
    return false;
  }
  return true;
}

function isUnsupportedPublicPostRequest(request: NextRequest): boolean {
  if (requestMethod(request) !== "POST") {
    return false;
  }
  const pathname = requestPathname(request);
  if (isApiPath(pathname)) {
    return false;
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (isMultipartContentType(contentType)) {
    return false;
  }
  return true;
}

export function middleware(request: NextRequest): NextResponse {
  try {
    if (isUnsupportedMultipartRequest(request)) {
      const contentType = (request.headers.get("content-type") || "").toLowerCase();
      logStructured({
        severity: "INFO",
        component: WWW_COMPONENT,
        event: "blocked_unsupported_multipart_request",
        method: requestMethod(request),
        pathname: requestPathname(request),
        classification: UNSUPPORTED_MULTIPART_CLASSIFICATION,
        app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
        has_boundary: contentType.includes("boundary="),
      });
      return new NextResponse("Unsupported multipart request.", {
        status: 415,
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": "text/plain; charset=utf-8",
        },
      });
    }

    if (isUnsupportedPublicPostRequest(request)) {
      logStructured({
        severity: "INFO",
        component: WWW_COMPONENT,
        event: "blocked_unsupported_public_post_request",
        method: requestMethod(request),
        pathname: requestPathname(request),
        classification: UNSUPPORTED_PUBLIC_POST_CLASSIFICATION,
        app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
      });
      return new NextResponse("Method not allowed.", {
        status: 405,
        headers: {
          "Allow": "GET, HEAD",
          "Cache-Control": "no-store",
          "Content-Type": "text/plain; charset=utf-8",
        },
      });
    }

    return NextResponse.next();
  } catch (error) {
    logStructured({
      severity: "ERROR",
      component: WWW_COMPONENT,
      event: "www_middleware_unexpected_exception",
      method: requestMethod(request),
      pathname: requestPathname(request),
      classification: "unexpected_middleware_exception",
      app_version: sanitizeAppVersion(process.env.NEXT_PUBLIC_APP_VERSION),
      error_message: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
