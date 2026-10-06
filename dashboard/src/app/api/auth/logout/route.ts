import { NextResponse } from "next/server";
import { CLEARED_COOKIE, getSession, SESSION_COOKIE } from "@/lib/auth/session";
import { forgetGuilds } from "@/lib/auth/guilds";
import { publicUrl } from "@/lib/env";

export const dynamic = "force-dynamic";

/** Sign out: the cookie is cleared server-side; the Discord token simply expires on its own. */
export async function POST() {
  const session = await getSession();
  if (session) forgetGuilds(session.userId);
  const response = NextResponse.redirect(publicUrl("/?reason=signed-out"), { status: 303 });
  response.cookies.set(SESSION_COOKIE, "", CLEARED_COOKIE);
  return response;
}
