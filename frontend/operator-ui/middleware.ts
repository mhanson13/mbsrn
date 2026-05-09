import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const MULTIPART_CONTENT_TYPE = "multipart/form-data";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH"]);

function isUnsupportedMultipartRequest(request: NextRequest): boolean {
  if (!MUTATING_METHODS.has(request.method.toUpperCase())) {
    return false;
  }
  if (request.headers.has("next-action")) {
    return false;
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes(MULTIPART_CONTENT_TYPE)) {
    return false;
  }
  const pathname = request.nextUrl.pathname || "/";
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return false;
  }
  return true;
}

export function middleware(request: NextRequest): NextResponse {
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
