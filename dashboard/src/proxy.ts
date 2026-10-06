import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "sprok_session";
const LEGAL_HOSTS: Record<string, string> = {
  [process.env.PRIVACY_HOST ?? "privacy.sprok.umbleh.dev"]: "/privacy",
  [process.env.TERMS_HOST ?? "terms.sprok.umbleh.dev"]: "/terms",
};

function csp(nonce: string): string {
  const dev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'${dev ? " 'unsafe-inline'" : ""}`,
    "img-src 'self' https://cdn.discordapp.com https://media.discordapp.net data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self' https://discord.com",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");
}

/**
 * Runs before every page: a fresh CSP nonce, the legal hostnames rewritten onto their pages, and an
 * optimistic sign-in redirect for the dashboard. The real session check happens in the layouts.
 */
export function proxy(request: NextRequest) {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "";
  const { pathname } = request.nextUrl;

  const legalPath = LEGAL_HOSTS[host.split(":")[0]];
  if (legalPath !== undefined && pathname !== legalPath) {
    // privacy.sprok.umbleh.dev serves only the privacy page, whatever path was asked for
    return NextResponse.rewrite(new URL(legalPath, request.url));
  }

  const wantsDashboard = pathname === "/dashboard" || pathname.startsWith("/g/");
  if (wantsDashboard && !request.cookies.has(SESSION_COOKIE)) {
    // not request.url: under the standalone server that is the bind address, not the public host
    const url = new URL("/", process.env.APP_URL ?? "https://sprok.umbleh.dev");
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const policy = csp(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|icon).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
