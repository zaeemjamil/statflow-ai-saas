import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { exceedsUploadLimit, isUploadRequest, tooLargeResponseBody } from "@/lib/upload-guard";

/**
 * Optimistic redirect only: checks that a session cookie is *present*.
 * It cannot validate the JWT (that secret lives in the backend); real
 * validation is the backend's 401 on every request, which the client
 * guard in (app)/layout.tsx also handles.
 */
const COOKIE = process.env.NEXT_PUBLIC_SESSION_COOKIE ?? "access_token";
const AUTH_PAGES = ["/login", "/register", "/forgot-password"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // API upload path only (see matcher): answer an oversized body with the backend-shaped
  // JSON 413 before Next starts buffering/proxying it. Everything else under /api/v1 is
  // never routed through this function.
  if (isUploadRequest(pathname, request.method)) {
    if (exceedsUploadLimit(request.headers.get("content-length"))) {
      return NextResponse.json(tooLargeResponseBody(), {
        status: 413,
        headers: { Connection: "close" },
      });
    }
    return NextResponse.next();
  }

  const hasSession = request.cookies.has(COOKIE);
  const isAuthPage = AUTH_PAGES.some((p) => pathname === p);

  if (!hasSession && !isAuthPage && pathname !== "/reset-password") {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (hasSession && isAuthPage) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)",
    "/api/v1/projects/:id/upload",
  ],
};
