import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { startLogin } from "@/lib/auth/discord";
import { clientIp, LIMITS, take } from "@/lib/rate-limit";

export const dynamic = "force-dynamic";

const TEN_MINUTES = 10 * 60;

/** Sends the user to Discord. State and the PKCE verifier ride along in a short-lived cookie. */
export async function GET(request: NextRequest) {
  const ip = await clientIp();
  const limit = take(`login:${ip}`, LIMITS.login);
  if (!limit.ok) {
    return new NextResponse("Too many sign-in attempts. Try again in a few minutes.", {
      status: 429,
      headers: { "Retry-After": String(Math.ceil(limit.retryAfterMs / 1000)) },
    });
  }
  const next = request.nextUrl.searchParams.get("next") ?? "/dashboard";
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
  const { url, state, codeVerifier } = await startLogin();
  const store = await cookies();
  const options = { httpOnly: true, secure: process.env.NODE_ENV !== "development", sameSite: "lax" as const, path: "/", maxAge: TEN_MINUTES };
  store.set("sprok_oauth", JSON.stringify({ state, codeVerifier, next: safeNext }), options);
  return NextResponse.redirect(url);
}
