import { botHealth } from "@/lib/bot/client";

/** Deep health: the process is up and the bot's internal api answers. For uptime monitors, not Docker. */
export async function GET() {
  const bot = await botHealth();
  const status = bot.ok ? 200 : 503;
  return Response.json({ ok: bot.ok, service: "sprok-dashboard", bot }, { status, headers: { "Cache-Control": "no-store" } });
}
