import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { avatarUrl, fetchMe, finishLogin } from "@/lib/auth/discord";
import { publicUrl } from "@/lib/env";
import { CLEARED_COOKIE, sealSession, SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

const Pending = z.object({ state: z.string().min(8), codeVerifier: z.string().min(32), next: z.string().startsWith("/") });

function failed(reason: string) {
  const url = publicUrl("/");
  url.searchParams.set("reason", reason);
  return NextResponse.redirect(url);
}

export async function GET(request: NextRequest) {
  const store = await cookies();
  const raw = store.get("sprok_oauth")?.value;
  store.set("sprok_oauth", "", CLEARED_COOKIE);
  const pending = raw ? Pending.safeParse(JSON.parse(raw)) : null;
  if (!pending?.success) return failed("no-state");

  let tokens;
  try {
    tokens = await finishLogin(request.nextUrl.searchParams, pending.data.state, pending.data.codeVerifier);
  } catch (error) {
    console.warn("discord callback rejected:", error instanceof Error ? error.message : error);
    return failed("denied");
  }
  if (!tokens.scope.split(" ").includes("guilds")) return failed("scopes");

  let me;
  try {
    me = await fetchMe(tokens.accessToken);
  } catch (error) {
    console.warn("discord /users/@me failed:", error instanceof Error ? error.message : error);
    return failed("discord-down");
  }
  const sealed = await sealSession({
    userId: me.id,
    username: me.username,
    displayName: me.global_name ?? me.username,
    avatar: avatarUrl(me),
    accessToken: tokens.accessToken,
    expiresAt: tokens.expiresAt,
  });
  const response = NextResponse.redirect(publicUrl(pending.data.next));
  response.cookies.set(SESSION_COOKIE, sealed, sessionCookieOptions(tokens.expiresAt));
  return response;
}
